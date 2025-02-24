package main

import (
    "fmt"
    "time"
    "net/http"
    "log"
    "context"
    //"encoding/base64"
    "encoding/json"

    "github.com/coreos/etcd/clientv3"
    "github.com/gin-gonic/gin"
    // "krake/pkg/api"
)

type Database struct {
    cli *clientv3.Client
    kv clientv3.KV
}

func new_database() *Database {
    db := new(Database)
    cli, err := clientv3.New(clientv3.Config{
        Endpoints:   []string{"localhost:2379"},
        // Endpoints: []string{"localhost:2379", "localhost:22379", "localhost:32379"}
        DialTimeout: 5 * time.Second,
    })
    if err != nil {
        log.Fatal(err)
    } else {
    	db.cli = cli
    }
    db.kv = clientv3.NewKV(db.cli)

    return db
}

func (db Database) get(key string) *clientv3.GetResponse {

	get_resp, err := db.kv.Get(context.TODO(), key)
	if err != nil {
		log.Fatal(err)
		// ESCALATE
	}
	return get_resp
}

func (db Database) put(key string, value string) *clientv3.PutResponse {

    put_resp, err := db.kv.Put(context.TODO(), key, value)
    if err != nil {
        log.Fatal(err)
        // ESCALATE
    }
    return put_resp
}

func (db Database) delete(key string) *clientv3.DeleteResponse {

    del_resp, err := db.kv.Delete(context.TODO(), key)
    if err != nil {
        log.Fatal(err)
        // ESCALATE
    }
    return del_resp
}

func (db Database) list(key string) *clientv3.GetResponse {

	range_resp, err := db.kv.Get(context.TODO(), key, clientv3.WithPrefix())
	if err != nil {
		log.Fatal(err)
		// ESCALATE
	}
	return range_resp
}

type Metadata struct {
    Name        string `json:"name"`
    Namespace   string `json:"namespace"`

    Uid         string `json:"uid"`
    Created     string `json:"created"`
    Modified    string `json:"modified"`
    Deleted     string `json:"deleted"`
}

type Verb string

const (
	Create      Verb = "create"
	Get         Verb = "get"
	Update      Verb = "update"
	Delete      Verb = "delete"
	List        Verb = "list"
	List_all    Verb = "list_all"
)

type Rule struct {
    Api         string      `json:"api"`
    Resources   []string    `json:"resources"`
    Namespaces  []string    `json:"namespaces"`
    Verbs       []Verb      `json:"verbs"`
}

type Role struct {
    Api         string      `json:"api" default0:"core"`
    Kind        string      `json:"kind" default0:"Role"`
    Metadata    Metadata    `json:"metadata"`
    Rules       []Rule      `json:"rules"`
}

type RoleBinding struct {
    Api         string      `json:"api" default0:"core"`
    Kind        string      `json:"kind" default0:"RoleBinding"`
    Metadata    Metadata    `json:"metadata"`
    Users       []string    `json:"users"`
    Roles       []string    `json:"roles"`
}


type CoreApi struct {

}

func (api CoreApi) create_role(c *gin.Context) {

    var body Role;

    if err := c.BindJSON(&body); err != nil {
        fmt.Println(err)
        // DO SOMETHING WITH THE ERROR
    }

    data, _ := json.Marshal(body)

	db := new_database()
	db.put("/core/roles/" + body.Metadata.Name, string(data))

    c.Status(http.StatusOK)
}

func (api CoreApi) read_role(c *gin.Context) {

	name := c.Param("name")

	db := new_database()
	get_resp := db.get("/core/roles/" + name)

	if len(get_resp.Kvs) == 0 {
	    c.Status(http.StatusNotFound)
	    return
	}

	c.Data(http.StatusOK, "application/json", get_resp.Kvs[0].Value)
}

func (api CoreApi) update_role(c *gin.Context) {

	name := c.Param("name")

    var body Role;

    if err := c.BindJSON(&body); err != nil {
        fmt.Println(err)
        // DO SOMETHING WITH THE ERROR
    }

    data, _ := json.Marshal(body)

	db := new_database()
	put_resp := db.put("/core/roles/" + name, string(data))
	if put_resp.Header.Revision == 0 {
	    c.Status(http.StatusNotFound)
	}

    c.Status(http.StatusOK)
}

func (api CoreApi) delete_role(c *gin.Context) {

	name := c.Param("name")

	db := new_database()
	del_resp := db.delete("/core/roles/" + name)
	if del_resp.Deleted == 0 {
	    c.Status(http.StatusNotFound)
	}

    c.Status(http.StatusOK)
}

func (api CoreApi) list_roles(c *gin.Context) {

	db := new_database()
	get_resp := db.list("/core/roles")

    var data []Role
	for _, elem := range get_resp.Kvs {
	    var rdata Role
	    json.Unmarshal(elem.Value, &rdata)
	    data = append(data, rdata)
	}

    c.IndentedJSON(http.StatusOK, data)
}

func (api CoreApi) createRoleBinding(c *gin.Context) {

    var body RoleBinding;

    if err := c.BindJSON(&body); err != nil {
        fmt.Println(err)
        // DO SOMETHING WITH THE ERROR
    }

    data, _ := json.Marshal(body)

	db := new_database()
	db.put("/core/rolebindings/" + body.Metadata.Name, string(data))

    c.Status(http.StatusOK)
}

func (api CoreApi) readRoleBinding(c *gin.Context) {

	name := c.Param("name")

	db := new_database()
	get_resp := db.get("/core/rolebindings/" + name)

	if len(get_resp.Kvs) == 0 {
	    c.Status(http.StatusNotFound)
	    return
	}

	c.Data(http.StatusOK, "application/json", get_resp.Kvs[0].Value)
}

func (api CoreApi) updateRoleBinding(c *gin.Context) {

	name := c.Param("name")

    var body RoleBinding;

    if err := c.BindJSON(&body); err != nil {
        fmt.Println(err)
        // DO SOMETHING WITH THE ERROR
    }

    data, _ := json.Marshal(body)

	db := new_database()
	put_resp := db.put("/core/rolebindings/" + name, string(data))
	if put_resp.Header.Revision == 0 {
	    c.Status(http.StatusNotFound)
	}

    c.Status(http.StatusOK)
}

func (api CoreApi) deleteRoleBinding(c *gin.Context) {

	name := c.Param("name")

	db := new_database()
	del_resp := db.delete("/core/rolebindings/" + name)
	if del_resp.Deleted == 0 {
	    c.Status(http.StatusNotFound)
	}

    c.Status(http.StatusOK)
}

func (api CoreApi) listRoleBindings(c *gin.Context) {

	db := new_database()
	get_resp := db.list("/core/rolebindings")

    var data []RoleBinding
	for _, elem := range get_resp.Kvs {
	    var rbdata RoleBinding
	    json.Unmarshal(elem.Value, &rbdata)
	    data = append(data, rbdata)
	}

    c.IndentedJSON(http.StatusOK, data)
}

func (api CoreApi) createMetric(c *gin.Context) {

    var body Metric;

    if err := c.BindJSON(&body); err != nil {
        fmt.Println(err)
        // DO SOMETHING WITH THE ERROR
    }

    data, _ := json.Marshal(body)

	db := new_database()
	db.put("/core/metrics/" + data.Metadata.Name, string(data))

    c.Status(http.StatusOK)
}

func (api CoreApi) readMetric(c *gin.Context) {

	name := c.Param("name")

	db := new_database()
	get_resp := db.get("/core/metrics/" + name)

	if len(get_resp.Kvs) == 0 {
	    c.Status(http.StatusNotFound)
	    return
	}

	c.Data(http.StatusOK, "application/json", get_resp.Kvs[0].Value)
}

func (api CoreApi) updateMetric(c *gin.Context) {

	name := c.Param("name")

    var body Metric;

    if err := c.BindJSON(&body); err != nil {
        fmt.Println(err)
        // DO SOMETHING WITH THE ERROR
    }

    data, _ := json.Marshal(body)

	db := new_database()
	put_resp := db.put("/core/metrics/" + name, string(data))
    if put_resp.Header.Revision == 0 {
	    c.Status(http.StatusNotFound)
	}

    c.Status(http.StatusOK)
}

func (api CoreApi) deleteMetric(c *gin.Context) {

	name := c.Param("name")

	db := new_database()
	del_resp := db.delete("/core/metrics/" + name)
	if del_resp.Deleted == 0 {
	    c.Status(http.StatusNotFound)
	}

    c.Status(http.StatusOK)
}

func (api CoreApi) listMetrics(c *gin.Context) {

	db := new_database()
	get_resp := db.list("/core/metrics/")

    var data []Metric
	for _, elem := range get_resp.Kvs {
	    var rdata Metric
	    json.Unmarshal(elem.Value, &rdata)
	    data = append(data, rdata)
	}

    c.IndentedJSON(http.StatusOK, data)
}


func (api CoreApi) create_metricsprovider(c *gin.Context) {

    var body Metricsprovider;

    if err := c.BindJSON(&body); err != nil {
        fmt.Println(err)
        // DO SOMETHING WITH THE ERROR
    }

    data, _ := json.Marshal(body)

	db := new_database()
	db.put("/core/metricsproviders/" + data.Metadata.Name, string(data))

    c.Status(http.StatusOK)
}

func (api CoreApi) read_metricsprovider(c *gin.Context) {

	name := c.Param("name")

	db := new_database()
	get_resp := db.get("/core/metricsproviders/" + name)

	if len(get_resp.Kvs) == 0 {
	    c.Status(http.StatusNotFound)
	    return
	}

    c.Data(http.StatusOK, "application/json", get_resp.Kvs[0].Value)
}

func (api CoreApi) update_metricsprovider(c *gin.Context) {

	name := c.Param("name")

    var body Metricsprovider;

    if err := c.BindJSON(&body); err != nil {
        fmt.Println(err)
        // DO SOMETHING WITH THE ERROR
    }

    data, _ := json.Marshal(body)

	db := new_database()
	put_resp := db.put("/core/metricsproviders/" + name, string(data))
	if put_resp.Header.Revision == 0 {
	    c.Status(http.StatusNotFound)
	}

    c.Status(http.StatusOK)
}

func (api CoreApi) delete_metricsprovider(c *gin.Context) {

	name := c.Param("name")

	db := new_database()
	del_resp := db.delete("/core/metricsproviders/" + name)
	if del_resp.Deleted == 0 {
	    c.Status(http.StatusNotFound)
	}

    c.Status(http.StatusOK)
}

func (api CoreApi) list_metricsproviders(c *gin.Context) {

	db := new_database()
	get_resp := db.get("/core/metricsproviders")

    var data []MetricsProvider
	for _, elem := range get_resp.Kvs {
	    var mpdata MetricsProvider
	    json.Unmarshal(elem.Value, &mpdata)
	    data = append(data, mpdata)
	}

    c.IndentedJSON(http.StatusOK, data)
}

func main() {
	router := gin.Default()

	core_api := CoreApi {}
	core := router.Group("/core")
	{
	    core.POST("/roles", core_api.create_role)
		core.GET("/roles/:name", core_api.read_role)
		core.PUT("/roles/:name", core_api.update_role)
		core.DELETE("/roles/:name", core_api.delete_role)
		core.GET("/roles", core_api.list_roles)
	    core.POST("/rolebindings", core_api.createRoleBinding)
		core.GET("/rolebindings/:name", core_api.readRoleBinding)
		core.PUT("/rolebindings/:name", core_api.updateRoleBinding)
		core.DELETE("/rolebindings/:name", core_api.deleteRoleBinding)
		core.GET("/rolebindings", core_api.listRoleBindings)
	    core.POST("/metrics", core_api.createMetric)
		core.GET("/metrics/:name", core_api.readMetric)
		core.PUT("/metrics/:name", core_api.updateMetric)
		core.DELETE("/metrics/:name", core_api.deleteMetric)
		core.GET("/metrics", core_api.listMetrics)
		core.POST("/metricsproviders", core_api.create_metricsprovider)
		core.GET("/metricsproviders/:name", core_api.read_metricsprovider)
		core.PUT("/metricsproviders/:name", core_api.update_metricsprovider)
		core.DELETE("/metricsproviders/:name", core_api.delete_metricsprovider)
		core.GET("/metricsproviders", core_api.list_metricsproviders)
	}

	s := &http.Server{
		Addr:           ":8080",
		Handler:        router,
		ReadTimeout:    10 * time.Second,
		WriteTimeout:   10 * time.Second,
		MaxHeaderBytes: 1 << 20,
	}
	s.ListenAndServe()
}